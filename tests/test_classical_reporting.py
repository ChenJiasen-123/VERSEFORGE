import copy
import json
import tempfile
import unittest
from pathlib import Path

from report_classical_evolution import validate_source_readings,report
from tests.test_classical_evolution import POEM, SOURCES


class SourceReportingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        job = self.root / 'jobs' / 'one'
        job.mkdir(parents=True)
        (job / 'result.json').write_text(json.dumps({'selected': {'poem': POEM}}), encoding='utf-8')
        self.binding = {'sources': SOURCES, 'jobs': [{'key': 'one'}]}
        self.row = {'job': 'one', 'poem_evidence': ['魂兮'], 'source_ids': ['s'],
                    'source_quotes': [{'source_id': 's', 'quote': '魂兮归来'}],
                    'relation': '召归与亡者的关系', 'compression': '唤归背景由语典承担',
                    'misuse': False, 'retelling': False, 'forced': False,
                    'supported': True, 'reason': '正文有实际唤归锚点；此测试只验证材料与判断记录一致。'}

    def check(self, row):
        return validate_source_readings(self.binding, {'readings': [row]}, self.root)

    def test_actual_poem_and_source_evidence_can_be_recorded(self):
        self.assertTrue(self.check(self.row)['one']['supported'])

    def test_fabricated_poem_or_source_quote_cannot_certify_allusion(self):
        for field, value in [('poem_evidence', ['诗中没有的词']),
                             ('source_quotes', [{'source_id': 's', 'quote': '典源没有的原话'}])]:
            with self.subTest(field=field):
                row = {**self.row, field: value}
                with self.assertRaises(ValueError):
                    self.check(row)

    def test_recognizable_but_misused_retold_or_forced_source_is_not_marked_supported(self):
        for issue in ('misuse', 'retelling', 'forced'):
            with self.subTest(issue=issue):
                row = copy.deepcopy(self.row)
                row[issue] = True
                with self.assertRaises(ValueError):
                    self.check(row)
                row['supported'] = False
                self.assertFalse(self.check(row)['one']['supported'])


class BlindReadingReportingTests(unittest.TestCase):
    def test_scores_alone_or_untyped_quotes_do_not_count_as_completed_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job=root/'jobs/one';job.mkdir(parents=True)
            binding={'experiment_sha256':'fixture','model':'fixture','arms':['classical_evolution'],
                     'topics':[{'id':'topic','prompt':'写七绝，须用典。','allusion_required':True}],
                     'sources':SOURCES,'jobs':[{'key':'one','topic_id':'topic','repetition':1,'arm':'classical_evolution'}]}
            result={'status':'candidate_with_unresolved_readings','selected':{'poem':POEM,'checks':{'meter':{'status':'unknown'}},'review':{'decision':'keep','allusion':{'supported':True}}},'budget':{'calls':1,'tokens':1,'elapsed_seconds':1}}
            (root/'experiment-binding.json').write_text(json.dumps(binding),encoding='utf-8')
            (job/'result.json').write_text(json.dumps(result),encoding='utf-8');report(root)
            packet=json.loads((root/'blind-packet.json').read_text(encoding='utf-8'))
            note={'blind_id':packet[0]['id'],'score':2,'worth_keeping':True,'quoted_evidence':['魂兮'],
                  'actual_experience':'唤归的愿望','main_problem':'局部措辞可修','allusion_guess_or_uncertainty':'招魂语典，仍待单独核对。','task_fit_non_allusion':'supported'}
            path=root/'assistant-blind-review.json'
            def save(n):path.write_text(json.dumps({'reviewer':'assistant','readings':[n]}),encoding='utf-8')
            save(note);self.assertEqual(report(root)['assistant_blind_reading']['status'],'complete')
            for change in ({'actual_experience':''},{'main_problem':'  '},
                           {'allusion_guess_or_uncertainty':None},{'quoted_evidence':'魂兮'},
                           {'quoted_evidence':['虚构引文']},{'worth_keeping':1},{'task_fit_non_allusion':None}):
                with self.subTest(change=change):
                    save({**note,**change})
                    with self.assertRaises(ValueError):report(root)
            save({**note,'task_fit_non_allusion':'violated'});r=report(root)
            self.assertFalse(r['research_acceptance']['classical_evolution']['checks']['no_selected_output_with_explicit_task_violation'])


if __name__ == '__main__':
    unittest.main()
