import json
import unittest
from poetry_agent.core import Task, Poem, check, compose, metrical_revision_feedback
from poetry_agent.client import MockClient
from poetry_agent.wujue import specification, evidence


LINES = ['暮雨侵苔徑', '疏燈照客衣', '寒窗聞葉落', '倚戶待人歸']


class WujueTests(unittest.TestCase):
    def test_profile_must_be_explicit_and_genre_specific(self):
        with self.assertRaises(ValueError): Task('雨', genre='wujue')
        with self.assertRaises(ValueError): Task('雨', wujue_pattern='ze_no_rhyme')
        with self.assertRaises(ValueError): Task('雨', genre='wujue', wujue_pattern='other')

    def test_first_line_rhyme_variants_preserve_remaining_couplets(self):
        for start in ['ping', 'ze']:
            a, b = specification(start + '_no_rhyme'), specification(start + '_rhyme')
            self.assertEqual(a['tones'][1:], b['tones'][1:])
            self.assertEqual(a['rhyme_lines_1based'], [2, 4])
            self.assertEqual(b['rhyme_lines_1based'], [1, 2, 4])
            self.assertTrue(all(len(line) == 5 for line in a['tones'] + b['tones']))

    def test_five_character_shape_does_not_accept_seven_character_lines(self):
        task = Task('雨', genre='wujue', wujue_pattern='ze_no_rhyme')
        self.assertEqual(check(Poem('夜', LINES), task), [])
        self.assertTrue(any('5个汉字' in issue for issue in check(Poem('夜', ['暮雨侵苔徑深深'] * 4), task)))

    def test_feet_are_fifth_characters_and_unknown_is_preserved(self):
        report = evidence(LINES, 'ze_no_rhyme')['basic_target_check']
        rhyme = report['findings'][-1]
        self.assertEqual([(x['line'], x['character'], x['text']) for x in rhyme['positions']], [(2, 5, '衣'), (4, 5, '歸')])
        self.assertEqual(report['status'], 'unknown')

    def test_wrong_tone_is_located_and_forwarded_to_repair(self):
        lines = ['春' + LINES[0][1:]] + LINES[1:]
        task = Task('雨', genre='wujue', wujue_pattern='ze_no_rhyme')
        feedback = metrical_revision_feedback({'lines': lines}, task)
        first = feedback['findings_to_review'][0]
        self.assertEqual((first['line'], first['character'], first['status']), (1, 1, 'failed'))
        self.assertEqual(first['expected_tone'], 'Z')

    def test_full_workflow_uses_five_character_target_and_retains_evidence(self):
        class Capture(MockClient):
            def complete(self, system, user, timeout):
                self.payload = json.loads(user)
                return super().complete(system, user, timeout)
        client = Capture()
        result = compose(Task('雨', genre='wujue', wujue_pattern='ze_no_rhyme'), client, aesthetic=True)
        self.assertEqual(result['poem']['lines'], LINES)
        self.assertEqual(client.payload['metrical_target']['tones'][0], 'ZZPPZ')
        self.assertEqual(result['prosody']['basic_target_check']['status'], 'unknown')
        self.assertEqual(result['prompt_version'], 'wujue-aesthetic-0.1')
        self.assertEqual(result['status'], 'constraints_passed')
