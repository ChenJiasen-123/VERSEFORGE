import json
from pathlib import Path
import unittest
from poetry_agent.core import Task, _metrical_target_and_report
from poetry_agent.meter_changes import compare_meter
from poetry_agent.prosody import Reading, validate


def report(text, pattern, lexicon):
    return validate([text], [pattern], [], lexicon, 'test target')


class MeterChangeTests(unittest.TestCase):
    def test_source_update_cannot_be_counted_as_poem_repair(self):
        before=report('甲','P',{'甲':[Reading('Z','a','source')]})
        after=report('甲','P',{'甲':[Reading('P','a','source')]})
        before['lexicon_provenance']={'main_sha256':'old'}
        after['lexicon_provenance']={'main_sha256':'new'}
        r=compare_meter(['甲'],['甲'],before,after)
        self.assertFalse(r['applicable']);self.assertEqual(r['reason'],'reading_source_revision_changed')
    def test_actual_repair_exposes_moved_failure_and_damage_to_passed_positions(self):
        path = Path(__file__).parents[1] / 'runs/metrical-feedback-trial-03/ze_rhyme-previous.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        before, after = [h['poem'] for h in data['history']]
        task = Task(**data['task'])
        result = compare_meter(before['lines'], after['lines'],
                               _metrical_target_and_report(before, task)[1],
                               _metrical_target_and_report(after, task)[1])
        self.assertTrue(result['applicable'])
        self.assertFalse(result['literary_quality_verified'])
        self.assertTrue(any(x.get('line') == 1 and x.get('character') == 5
                            for x in result['failures_now_unknown']))
        self.assertTrue(any(x.get('line') == 1 and x.get('character') == 1
                            for x in result['passed_checks_lost']))
        self.assertEqual(result['fixed_failures'], [])

    def test_different_words_with_same_confirmed_tone_are_not_regressions(self):
        lexicon = {'甲': [Reading('P', 'one', 'test')], '乙': [Reading('P', 'one', 'test')]}
        result = compare_meter(['甲'], ['乙'], report('甲', 'P', lexicon), report('乙', 'P', lexicon))
        self.assertEqual(result['passed_checks_lost'], [])
        self.assertNotEqual(result['before_body_sha256'], result['after_body_sha256'])

    def test_missing_form_is_not_a_fixed_failure(self):
        lexicon = {'甲': [Reading('Z', 'one', 'test')]}
        result = compare_meter(['甲'], ['乙'], report('甲', 'P', lexicon), report('乙', 'P', lexicon))
        self.assertEqual(len(result['failures_now_unknown']), 1)
        self.assertEqual(result['fixed_failures'], [])

    def test_mismatched_target_and_bad_shape_are_not_compared(self):
        lexicon = {'甲': [Reading('P', 'one', 'test')]}
        before = report('甲', 'P', lexicon)
        for after, lines in ((report('甲', 'Z', lexicon), ['甲']),
                             (report('甲甲', 'P', lexicon), ['甲甲'])):
            self.assertFalse(compare_meter(['甲'], lines, before, after)['applicable'])

    def test_report_from_different_body_cannot_be_silently_reused(self):
        lexicon = {'甲': [Reading('P', 'one', 'test')]}
        before = report('甲', 'P', lexicon)
        with self.assertRaises(ValueError):
            compare_meter(['乙'], ['甲'], before, before)

    def test_ci_tone_and_rhyme_tone_changes_remain_separate_checks(self):
        before = {'lines': ['新雨歇', '小巷水聲中', '青石階前苔色活', '賣花聲過小橋東', '濕燕避簷風']}
        after = {'lines': before['lines'][:-1] + ['濕燕避簷夢']}
        task = Task('雨後', genre='ci', ci_profile='baixiang_yijiangnan_liyu')
        result = compare_meter(before['lines'], after['lines'],
                               _metrical_target_and_report(before, task)[1],
                               _metrical_target_and_report(after, task)[1])
        changed = [x for x in result['passed_checks_lost'] if x.get('line') == 5 and x.get('character') == 5]
        self.assertEqual({x['check'] for x in changed}, {'tone', 'rhyme'})
        self.assertEqual({x['check']: x['after_status'] for x in changed},
                         {'tone': 'unknown', 'rhyme': 'failed'})

