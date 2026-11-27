import copy
import json
import tempfile
import unittest
from pathlib import Path

from report_classical_evolution import validate_source_readings
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


if __name__ == '__main__':
    unittest.main()
