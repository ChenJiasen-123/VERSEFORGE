import unittest
from poetry_agent.core import Task, Poem, check


class CiTests(unittest.TestCase):
    def test_same_total_length_cannot_hide_wrong_line_breaks(self):
        task = Task('题', genre='ci', ci_profile='baixiang_yijiangnan_liyu')
        from poetry_agent.ci import check_shape
        self.assertEqual(check_shape(['春'*n for n in [3,5,7,7,5]], task.ci_profile), [])
        self.assertTrue(check(Poem('题', ['春'*n for n in [4,4,7,7,5]]), task))

    def test_matching_lengths_cannot_hide_tone_mismatch(self):
        from poetry_agent.ci import evidence
        lines = ['東'*n for n in [3,5,7,7,5]]
        r = evidence(lines, 'baixiang_yijiangnan_liyu')
        self.assertEqual(r['tone_check']['status'], 'failed')
        self.assertEqual(r['rhyme_status'], 'pass')
        self.assertEqual(r['status'], 'unknown')

    def test_ci_requires_exact_profile(self):
        with self.assertRaises(ValueError):
            Task('题', genre='ci')
        with self.assertRaises(ValueError):
            Task('题', ci_profile='baixiang_yijiangnan_liyu')
