import unittest
from poetry_agent.rhyme_data import lookup_excerpt, qijue_evidence


class RhymeDataTests(unittest.TestCase):
    def test_selected_target_reports_tone_mismatch_without_global_certificate(self):
        report = qijue_evidence(['東' * 7] * 4, 'ping_rhyme')
        self.assertEqual(report['basic_target_check']['status'], 'failed')
        self.assertEqual(report['status'], 'unknown')
        findings = report['basic_target_check']['findings']
        self.assertTrue(any(f.get('character') == 3 and f['status'] == 'failed' for f in findings))

    def test_selected_target_problems_reach_revision_feedback(self):
        from poetry_agent.core import Poem, Task, check
        task = Task('测试', genre='qijue', qijue_pattern='ping_rhyme')
        self.assertTrue(check(Poem('测试', ['東' * 7] * 4), task))
        self.assertEqual(check(Poem('测试', ['東' * 7] * 4), Task('测试', genre='qijue')), [])

    def test_shared_membership_does_not_certify_rhyme(self):
        report = qijue_evidence(['春夜', '蛙。', '雨中', '花。'])
        self.assertIn('下平聲六麻', report['lines_2_4_shared_attested_ping_groups'])
        self.assertEqual(report['status'], 'unknown')
        self.assertEqual(report['feet'][1]['character'], '蛙')

    def test_complete_group_inventory(self):
        import json
        from pathlib import Path
        groups = json.loads((Path(__file__).parents[1] / 'poetry_agent/data/pingshui-excerpts.json').read_text(encoding='utf-8'))['groups']
        self.assertEqual(len({g['name'] for g in groups}), 106)
        for prefix, expected in [('上平聲', 15), ('下平聲', 15), ('上聲', 29), ('去聲', 30), ('入聲', 17)]:
            self.assertEqual(sum(g['name'].startswith(prefix) for g in groups), expected)
    def test_attested_membership_does_not_imply_unique_reading(self):
        result = lookup_excerpt('東')
        self.assertEqual(result['memberships'][0]['rhyme'], '上平聲一東')
        self.assertFalse(result['reading_resolved'])

    def test_unlisted_character_is_not_declared_absent_from_rhyme_book(self):
        result = lookup_excerpt('🙂')
        self.assertEqual(result['memberships'], [])
        self.assertEqual(result['coverage'], 'partial')
        self.assertFalse(result['reading_resolved'])

    def test_frog_retains_both_attested_groups(self):
        result = lookup_excerpt('蛙')
        self.assertEqual({g['rhyme'] for g in result['memberships']}, {'上平聲九佳', '下平聲六麻'})
        self.assertFalse(result['reading_resolved'])
