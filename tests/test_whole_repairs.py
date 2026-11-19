import json
import unittest
from poetry_agent.core import Task
from poetry_agent.lushi import specification
from poetry_agent.whole_repairs import propose_whole_repair
from poetry_agent.context_review import body_hash


class Client:
    def __init__(self, poem): self.poem, self.calls = poem, []
    def complete(self, system, user, **kwargs):
        self.calls.append(json.loads(user))
        return {'content': json.dumps(self.poem)}


class WholeRepairTests(unittest.TestCase):
    def fixture(self):
        lines = [r.translate(str.maketrans({'P': '春', 'Z': '雨'}))
                 for r in specification('wulv', 'ze_no_rhyme')['tones']]
        return {'title': '机械测试', 'lines': lines}

    def test_eight_line_proposal_is_checked_and_never_auto_adopted(self):
        poem = self.fixture()
        client = Client(poem)
        result = propose_whole_repair(poem, Task('夜', genre='wulv', lushi_pattern='ze_no_rhyme'), client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result['body_sha256'], body_hash(poem['lines']))
        self.assertEqual(result['target_check']['status'], 'pass')
        self.assertFalse(result['automatically_adopted'])
        self.assertFalse(result['literary_quality_verified'])
        self.assertEqual(result['parallelism_status'], 'unknown')

    def test_failed_proposal_is_preserved_and_not_called_passed(self):
        original = self.fixture()
        broken = {'title': '机械测试', 'lines': original['lines'][:4]}
        result = propose_whole_repair(original, Task('夜', genre='wulv', lushi_pattern='ze_no_rhyme'), Client(broken))
        self.assertEqual(result['status'], 'proposal_checked')
        self.assertEqual(result['target_check']['status'], 'failed')
        self.assertEqual(result['original'], original)
        self.assertTrue(result['issues'])

    def test_invalid_settings_and_modern_rejected_before_call(self):
        client = Client(self.fixture())
        for kwargs in ({'budget': 0}, {'max_tokens': True}, {'thinking': 'auto'}):
            with self.assertRaises(ValueError): propose_whole_repair(self.fixture(), Task('夜'), client, **kwargs)
        with self.assertRaises(ValueError): propose_whole_repair(self.fixture(), Task('夜'), client)
        self.assertEqual(client.calls, [])
