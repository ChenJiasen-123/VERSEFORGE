import json
import unittest
from poetry_agent.core import Task
from poetry_agent.line_repairs import propose_line_repairs

# Mechanical fixtures, not literary examples or claimed generated poems.
GOOD = ['雨雨春春雨', '春春雨雨春', '春春春雨雨', '雨雨雨春春']
BAD = ['春雨春春雨'] + GOOD[1:]


class Reply:
    def __init__(self, rows): self.rows, self.calls = rows, 0
    def complete(self, system, user, **kwargs):
        self.calls += 1
        self.payload = json.loads(user)
        self.settings = kwargs
        return {'content': json.dumps({'line_options': self.rows}, ensure_ascii=False)}


class LineRepairTests(unittest.TestCase):
    def task(self, **kwargs):
        return Task('机械检查夹具', genre='wujue', wujue_pattern='ze_no_rhyme', **kwargs)

    def test_checked_candidate_preserves_other_lines_and_original(self):
        client = Reply([{'line': 1, 'options': [GOOD[0]]}])
        result = propose_line_repairs({'title': 'fixture', 'lines': BAD}, self.task(), client)
        self.assertEqual(result['candidates'][0]['poem']['lines'], GOOD)
        self.assertEqual(result['original']['lines'], BAD)
        self.assertEqual(result['requested_lines'], [1])
        self.assertFalse(result['automatically_adopted'])
        self.assertEqual(client.calls, 1)
        self.assertTrue(any(x['lines'] == BAD for x in result['combination_audit']))

    def test_wrong_options_do_not_create_a_checked_candidate(self):
        result = propose_line_repairs({'title': 'fixture', 'lines': BAD}, self.task(),
                                     Reply([{'line': 1, 'options': ['春春春春春']}]))
        self.assertEqual(result['status'], 'no_fully_checked_option')
        self.assertEqual(result['candidates'], [])

    def test_unrequested_line_and_boolean_line_are_rejected(self):
        for line in (2, True):
            with self.assertRaises(ValueError):
                propose_line_repairs({'title': 'fixture', 'lines': BAD}, self.task(),
                                     Reply([{'line': line, 'options': [GOOD[0]]}]))

    def test_latin_suffix_is_not_stripped_to_obtain_a_passing_line(self):
        result = propose_line_repairs({'title': 'fixture', 'lines': BAD}, self.task(),
                                     Reply([{'line': 1, 'options': [GOOD[0] + 'abc']}]))
        self.assertEqual(len(result['rejected_options']), 1)
        self.assertEqual(result['candidates'], [])

    def test_required_phrase_is_rechecked_after_merging(self):
        result = propose_line_repairs({'title': 'fixture', 'lines': BAD}, self.task(required_words=[BAD[0]]),
                                     Reply([{'line': 1, 'options': [GOOD[0]]}]))
        self.assertEqual(result['candidates'], [])
        self.assertTrue(all(x['issues'] for x in result['combination_audit']))

    def test_unknown_is_optional_and_is_not_relabelled_a_known_error(self):
        seed = ['空雨春春雨'] + GOOD[1:]
        client = Reply([{'line': 1, 'options': [GOOD[0]]}])
        result = propose_line_repairs({'title': 'fixture', 'lines': seed}, self.task(), client)
        self.assertEqual(client.calls, 0)
        self.assertEqual(result['status'], 'no_requested_repairs')
        result = propose_line_repairs({'title': 'fixture', 'lines': seed}, self.task(), client, include_unknown=True)
        self.assertEqual(result['original_target_check']['status'], 'unknown')
        self.assertTrue(result['candidates'])

    def test_unsupported_task_fails_before_any_call(self):
        client = Reply([])
        with self.assertRaises(ValueError):
            propose_line_repairs({'title': 'fixture', 'lines': BAD}, Task('现代诗'), client)
        self.assertEqual(client.calls, 0)

    def test_malformed_original_shape_fails_before_any_call(self):
        client = Reply([])
        with self.assertRaises(ValueError):
            propose_line_repairs({'title': 'fixture', 'lines': [BAD[0] + 'abc'] + BAD[1:]}, self.task(), client)
        self.assertEqual(client.calls, 0)

    def test_explicit_thinking_setting_reaches_only_proposal_call(self):
        client = Reply([{'line': 1, 'options': [GOOD[0]]}])
        result = propose_line_repairs({'title': 'fixture', 'lines': BAD}, self.task(), client, thinking='enabled', max_tokens=8192)
        self.assertEqual(client.settings['thinking'], 'enabled')
        self.assertEqual(result['proposal_thinking'], 'enabled')
        self.assertEqual(client.settings['max_tokens'], 8192)
        self.assertEqual(client.calls, 1)

    def test_no_known_conflicts_with_unknown_readings_is_a_separate_pending_list(self):
        seed = [BAD[0], GOOD[1], '空春春雨雨', GOOD[3]]
        result = propose_line_repairs({'title': 'fixture', 'lines': seed}, self.task(),
                                     Reply([{'line': 1, 'options': [GOOD[0]]}]))
        self.assertEqual(result['status'], 'context_review_required')
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['pending_context_count'], 1)
        self.assertEqual(result['pending_context_candidates'][0]['target_check']['status'], 'unknown')

