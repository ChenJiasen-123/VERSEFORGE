import unittest
from poetry_agent.text_structure import inspect_structure


class StructureTests(unittest.TestCase):
    def test_exact_repetition_is_reported_without_rhyme_claim(self):
        r = inspect_structure(['我没有听见。', '你也没有听见。'])
        self.assertIn({'fragment': '没有听见', 'lines': [1, 2]}, r['cross_line_literal_repetitions'])
        self.assertEqual(r['line_end_characters'][0]['last_character'], '见')
        self.assertNotIn('rhyme_passed', r)

    def test_repeated_action_does_not_invent_literal_repeat(self):
        r = inspect_structure(['把伞收了又撑开。', '雨珠落在鞋面。'])
        self.assertEqual(r['cross_line_literal_repetitions'], [])

    def test_punctuation_does_not_join_into_nonexistent_phrase(self):
        r = inspect_structure(['我，等待。', '我等待。'])
        self.assertNotIn({'fragment': '我等待', 'lines': [1, 2]}, r['cross_line_literal_repetitions'])
