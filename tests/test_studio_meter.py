import unittest
from poetry_agent.studio import final_meter, run_studio
from poetry_agent.core import Task
from poetry_agent.context_review import body_hash
from tests.test_studio import Client, brief


class StudioMeterTests(unittest.TestCase):
    def test_modern_has_no_classical_meter_result(self):
        self.assertIsNone(final_meter({'title': '夜', 'lines': ['雨下着']}, Task('雨')))

    def test_unknown_findings_are_not_hidden_by_empty_hard_errors(self):
        poem = {'title': '夜', 'lines': ['暮雨侵苔徑', '疏燈照客衣', '寒窗聞葉落', '倚戶待人歸']}
        meter = final_meter(poem, Task('雨', genre='wujue', wujue_pattern='ze_no_rhyme'))
        self.assertEqual(meter['report']['status'], 'unknown')
        self.assertTrue(any(x['status'] == 'unknown' for x in meter['report']['findings']))
        self.assertFalse(meter['overall_meter_certified'])
        self.assertEqual(meter['body_sha256'], body_hash(poem['lines']))

    def test_selected_revision_gets_fresh_evidence(self):
        original = {'title': '夜', 'lines': ['春雨侵苔徑', '疏燈照客衣', '寒窗聞葉落', '倚戶待人歸']}
        revised = {'title': '夜', 'lines': ['暮雨侵苔徑', '疏燈照客衣', '寒窗聞葉落', '倚戶待人歸']}
        client = Client([brief(genre='wujue', pattern='ze_no_rhyme', requirements=[]),
                         original, revised])
        result = run_studio('写一首五绝', client=client)
        meter = result['checks']['final_meter']
        self.assertEqual(result['poem'], revised)
        self.assertEqual(meter['lines'], revised['lines'])
        self.assertEqual(meter['body_sha256'], body_hash(revised['lines']))
        self.assertNotEqual(meter['body_sha256'], body_hash(original['lines']))
        self.assertFalse(any(x.get('line') == 1 and x.get('character') == 1
                             and x['status'] == 'failed' for x in meter['report']['findings']))

    def test_lushi_eighth_line_and_ci_rhyme_are_included(self):
        from poetry_agent.lushi import specification
        rows = [row.translate(str.maketrans({'P': '春', 'Z': '雨'}))
                for row in specification('qilv', 'ze_no_rhyme')['tones']]
        rows[7] = rows[7][:-1] + '東'
        meter = final_meter({'title': '机械测试', 'lines': rows},
                            Task('夜', genre='qilv', lushi_pattern='ze_no_rhyme'))
        self.assertEqual(meter['report']['status'], 'failed')
        self.assertEqual(meter['report']['findings'][-1]['positions'][-1]['line'], 8)
        meter = final_meter({'title': '雨', 'lines': ['新雨歇', '小巷水聲中', '青石階前苔色活', '賣花聲過小橋東', '濕燕避簷風']},
                            Task('雨', genre='ci', ci_profile='baixiang_yijiangnan_liyu'))
        self.assertEqual({x['check'] for x in meter['report']['findings']}, {'tone', 'rhyme'})
