import unittest
from poetry_agent.lushi import specification, evidence
from poetry_agent.core import Task, Poem, check


class LushiTests(unittest.TestCase):
    # Mechanical tone fixtures, not literary examples.
    def lines(self, genre, profile):
        return [row.translate(str.maketrans({'P': '春', 'Z': '雨'}))
                for row in specification(genre, profile)['tones']]

    def test_full_eight_line_targets(self):
        expected = {
            ('wulv', 'ze'): 'ZZPPZ PPZZP PPPZZ ZZZPP ZZPPZ PPZZP PPPZZ ZZZPP',
            ('wulv', 'ping'): 'PPPZZ ZZZPP ZZPPZ PPZZP PPPZZ ZZZPP ZZPPZ PPZZP',
            ('qilv', 'ze'): 'ZZPPPZZ PPZZZPP PPZZPPZ ZZPPZZP ZZPPPZZ PPZZZPP PPZZPPZ ZZPPZZP',
            ('qilv', 'ping'): 'PPZZPPZ ZZPPZZP ZZPPPZZ PPZZZPP PPZZPPZ ZZPPZZP ZZPPPZZ PPZZZPP'}
        first_rhyme = {('wulv', 'ze'): 'ZZZPP', ('wulv', 'ping'): 'PPZZP',
                       ('qilv', 'ze'): 'ZZPPZZP', ('qilv', 'ping'): 'PPZZZPP'}
        for (genre, start), matrix in expected.items():
            for suffix in ('_no_rhyme', '_rhyme'):
                rows = matrix.split()
                if suffix == '_rhyme': rows[0] = first_rhyme[genre, start]
                target = specification(genre, start + suffix)
                self.assertEqual(target['tones'], rows)
                self.assertEqual(target['rhyme_lines_1based'], [2, 4, 6, 8] if suffix == '_no_rhyme' else [1, 2, 4, 6, 8])
                self.assertTrue(rows[4].endswith('Z'))

    def test_late_rhyme_conflict_is_checked_and_parallelism_is_unverified(self):
        for genre in ('wulv', 'qilv'):
            rows = self.lines(genre, 'ze_no_rhyme')
            report = evidence(rows, genre, 'ze_no_rhyme')
            self.assertEqual(report['basic_target_check']['status'], 'pass')
            self.assertEqual(report['parallelism']['status'], 'unknown')
            for index in (5, 7):
                changed = rows.copy()
                changed[index] = changed[index][:-1] + '東'
                self.assertEqual(evidence(changed, genre, 'ze_no_rhyme')['basic_target_check']['status'], 'failed')

    def test_explicit_profile_and_eight_line_shape(self):
        for genre in ('wulv', 'qilv'):
            with self.assertRaises(ValueError): Task('夜', genre=genre)
            task = Task('夜', genre=genre, lushi_pattern='ze_no_rhyme')
            rows = self.lines(genre, 'ze_no_rhyme')
            self.assertEqual(check(Poem('机械测试', rows), task), [])
            self.assertTrue(check(Poem('机械测试', rows[:4]), task))
        with self.assertRaises(ValueError): Task('夜', lushi_pattern='ze_no_rhyme')
