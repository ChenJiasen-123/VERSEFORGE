import json
import unittest
from poetry_agent.requirement_checks import review_requirements, safe_review

PROMPT = '诗中包含你写给十年后自己的一句话。'
POEM = {'title': '备份', 'lines': ['我把那句话写在便签里，', '收件人：十年后的你。']}


class Client:
    def __init__(self, rows): self.rows = rows
    def complete(self, *args, **kwargs): return {'content': json.dumps({'checks': self.rows}, ensure_ascii=False)}


def row(**updates):
    value = {'id': 'r1', 'status': 'satisfied', 'source_quote': PROMPT[:-1],
             'evidence': '', 'reason': '模型判断'}
    value.update(updates)
    return value


class RequirementTests(unittest.TestCase):
    def run_check(self, rows, poem=POEM):
        return review_requirements(PROMPT, poem, [PROMPT[:-1]], Client(rows))

    def test_empty_report_does_not_mean_all_requirements_met(self):
        result = self.run_check([])
        self.assertFalse(result['complete'])
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['checks'][0]['status'], 'uncertain')

    def test_presence_cannot_be_satisfied_without_textual_evidence(self):
        self.assertEqual(self.run_check([row()])['checks'][0]['evidence_issue'], 'missing_presence_evidence')

    def test_mentioning_that_sentence_is_not_proof_of_its_content(self):
        result = self.run_check([row(evidence='我把那句话写在便签里，')])
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['checks'][0]['status'], 'uncertain')

    def test_fabricated_quote_is_not_presented_as_poem_text(self):
        result = self.run_check([row(evidence='不要忘记我')])
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['checks'][0]['evidence'], '')

    def test_actual_passage_can_support_a_presence_claim(self):
        poem = {'title': '信', 'lines': ['“十年后，请记得给花换水。”']}
        result = self.run_check([row(evidence=poem['lines'][0])], poem)
        self.assertTrue(result['confirmed'])
        self.assertFalse(result['semantics_verified'])

    def test_recipient_metadata_does_not_establish_the_missing_message(self):
        result = self.run_check([row(evidence='收件人：十年后的你。')])
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['checks'][0]['evidence_issue'], 'metadata_not_message_evidence')

    def test_source_reference_uses_program_supplied_original_text(self):
        poem = {'title': '信', 'lines': ['“十年后，请记得给花换水。”']}
        value = row(evidence=poem['lines'][0], source_id='s1', source_quote='伪造的另一个原题')
        result = self.run_check([value], poem)
        self.assertEqual(result['checks'][0]['source_quote'], PROMPT[:-1])
        self.assertTrue(result['confirmed'])

    def test_hallucinated_source_requirement_cannot_trigger_rewrite(self):
        result = self.run_check([row(status='violated', source_quote='必须出现短信')])
        self.assertEqual(result['violations'], [])

    def test_duplicate_ids_make_review_incomplete(self):
        result = safe_review(PROMPT, POEM, [PROMPT[:-1]], Client([row(), row()]))
        self.assertFalse(result['confirmed'])
        self.assertFalse(result['complete'])

    def test_negative_absence_requirement_does_not_need_presence_quote(self):
        prompt = '诗中不得出现器物名称。'
        result = review_requirements(prompt, {'title': '杯', 'lines': ['旧痕还在']}, [prompt],
            Client([row(source_quote=prompt, evidence='', reason='正文没有出现名称。')]))
        self.assertTrue(result['confirmed'])

class EvidenceReferenceTests(unittest.TestCase):
    def test_reference_retrieves_exact_line_and_rejects_retyped_join(self):
        prompt='正文须包含一次开门动作。'
        poem={'title':'旧物','lines':['铜牙入孔，','推门见月。']}
        rows=[{'id':'r1','status':'satisfied','source_id':'s1','evidence_id':'p2',
               'evidence':'铜牙入孔，推门见月。','reason':'第二句实际写出推门。'}]
        report=review_requirements(prompt,poem,[prompt[:-1]],Client(rows))
        self.assertTrue(report['confirmed'])
        self.assertEqual(report['checks'][0]['evidence'],'推门见月。')

    def test_unknown_reference_does_not_fall_back_to_plausible_quote(self):
        rows=[row(evidence_id='p999',evidence='我把那句话写在便签里，')]
        with self.assertRaisesRegex(ValueError,'证据编号无效'):
            review_requirements(PROMPT,POEM,[PROMPT[:-1]],Client(rows))

    def test_reference_does_not_make_placeholder_a_real_utterance(self):
        report=review_requirements(PROMPT,POEM,[PROMPT[:-1]],Client([row(evidence_id='p1')]))
        self.assertFalse(report['confirmed'])

class ReferenceOnlyResponseTests(unittest.TestCase):
    def test_reference_only_response_is_valid_without_retyped_quote(self):
        prompt='正文必须出现开门。'
        poem={'title':'题','lines':['开门见月。']}
        rows=[{'id':'r1','status':'satisfied','source_id':'s1','evidence_id':'p1','reason':'第一句写出了开门。'}]
        report=review_requirements(prompt,poem,[prompt[:-1]],Client(rows))
        self.assertTrue(report['confirmed'])
        self.assertEqual(report['checks'][0]['evidence'],'开门见月。')
