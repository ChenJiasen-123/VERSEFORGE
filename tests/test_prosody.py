import unittest
from poetry_agent.prosody import Reading, validate


class ProsodyTests(unittest.TestCase):
    def test_context_override_affects_only_one_occurrence(self):
        data = {'甲': [Reading('P', 'a', 'table'), Reading('Z', 'b', 'table')]}
        result = validate(['甲甲'], ['PP'], [], data, 'test', {(0, 0): [Reading('P', 'a', 'review')]})
        self.assertEqual(result['findings'][0]['status'], 'pass')
        self.assertEqual(result['findings'][1]['status'], 'unknown')
    def test_unconstrained_tone_is_not_a_resolved_reading(self):
        data = {'甲': [Reading('P', 'a', 'test'), Reading('Z', 'b', 'test')],
                '乙': [Reading('Z', 'a', 'test')]}
        r = validate(['甲乙'], ['XZ'], [(0, 0), (0, 1)], data, 'synthetic-test')
        self.assertEqual(r['findings'][0]['status'], 'not_required')
        self.assertFalse(r['findings'][0]['reading_resolved'])
        self.assertEqual(r['findings'][-1]['status'], 'unknown')

    def test_unconstrained_missing_character_does_not_claim_known_tone(self):
        r = validate(['甲乙'], ['XZ'], [], {}, 'synthetic-test')
        self.assertEqual(r['findings'][0]['status'], 'not_required')
        self.assertEqual(r['findings'][0]['attested_tones'], [])
        self.assertEqual(r['findings'][1]['status'], 'unknown')

    def test_multiple_groups_can_share_known_tone_without_resolving_rhyme(self):
        data = {'甲': [Reading('Z', 'a', 'test'), Reading('Z', 'b', 'test')],
                '乙': [Reading('Z', 'a', 'test')]}
        r = validate(['甲乙'], ['ZZ'], [(0, 0), (0, 1)], data, 'synthetic-test')
        self.assertEqual(r['findings'][0]['status'], 'pass')
        self.assertEqual(r['findings'][-1]['status'], 'unknown')
        self.assertEqual(r['status'], 'unknown')
    # Synthetic symbols deliberately avoid posing test fixtures as a rhyme book.
    def test_unknown_is_never_passed(self):
        r = validate(['甲乙'], ['PP'], [(0, 0), (0, 1)], {}, 'synthetic-test')
        self.assertEqual(r['status'], 'unknown')

    def test_ambiguous_reading_is_not_picked_to_fit(self):
        data = {'甲': [Reading('P', 'a', 'test'), Reading('Z', 'b', 'test')],
                '乙': [Reading('P', 'a', 'test')]}
        r = validate(['甲乙'], ['PP'], [(0, 0), (0, 1)], data, 'synthetic-test')
        self.assertEqual(r['status'], 'unknown')
        self.assertEqual(r['findings'][0]['kind'], 'ambiguous_reading')

    def test_tone_and_rhyme_failures_are_located(self):
        data = {'甲': [Reading('Z', 'a', 'test')], '乙': [Reading('P', 'b', 'test')]}
        r = validate(['甲乙'], ['PP'], [(0, 0), (0, 1)], data, 'synthetic-test')
        self.assertEqual(r['status'], 'failed')
        self.assertEqual(r['findings'][0]['character'], 1)
        self.assertEqual(r['findings'][-1]['status'], 'failed')
        self.assertEqual(r['findings'][-1]['positions'], [
            {'line': 1, 'character': 1, 'text': '甲', 'resolved_group': 'a'},
            {'line': 1, 'character': 2, 'text': '乙', 'resolved_group': 'b'}])
