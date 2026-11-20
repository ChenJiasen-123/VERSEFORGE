import json
import unittest
from pathlib import Path
from poetry_agent.requirement_checks import review_requirements, ensure_content_requirement
from poetry_agent.studio import run_studio
from tests.test_requirement_checks import Client, row
from tests.test_studio import Client as SequenceClient, brief


CASE=json.loads((Path(__file__).parent/'fixtures/returned-letter.json').read_text(encoding='utf-8'))
REQ='包含你写给十年后自己的一句话'


class MessageFlowTests(unittest.TestCase):
    def checked(self,evidence,poem=None,requirement=REQ):
        return review_requirements(CASE['prompt'],poem or CASE['poem'],[requirement],
            Client([row(source_id='s0',evidence=evidence)]))

    def test_actual_user_poem_does_not_pass_by_mentioning_a_sentence(self):
        r=self.checked(CASE['poem']['lines'][0])
        self.assertFalse(r['confirmed']);self.assertEqual(len(r['repair_requests']),1)

    def test_narrator_question_and_system_text_do_not_replace_message(self):
        for index,issue in [(13,'narrator_question_not_explicit_message'),(14,'system_text_not_human_message')]:
            r=self.checked(CASE['poem']['lines'][index])
            self.assertEqual(r['checks'][0]['evidence_issue'],issue)
            self.assertEqual(len(r['repair_requests']),1)

    def test_combined_prohibition_does_not_disable_positive_content_check(self):
        r=self.checked(CASE['poem']['lines'][0],requirement=REQ+'，两者不得互相解释')
        self.assertFalse(r['confirmed']);self.assertTrue(r['repair_requests'])

    def test_quoted_or_unquoted_real_message_is_allowed(self):
        for line in ['我把一句话写进信里：“十年后，请别急着道歉。”',
                     '十年后的你，还会替今天的我脸红吗？']:
            r=self.checked(line,{'title':'信','lines':[line]})
            self.assertTrue(r['confirmed']);self.assertFalse(r['repair_requests'])

    def test_missing_extracted_obligation_is_restored_without_turning_optional_into_mandatory(self):
        self.assertEqual(len(ensure_content_requirement(CASE['prompt'],['不超过30行'])),2)
        self.assertEqual(ensure_content_requirement('不必在诗中包含写给自己的一句话。',[]),[])

    def test_uncertain_content_guard_triggers_one_repair_and_recheck(self):
        bad={'title':'信','lines':[CASE['poem']['lines'][0]]}
        good={'title':'信','lines':['我写：“十年后，请别急着道歉。”']}
        initial={'checks':[row(source_id='s0',evidence=bad['lines'][0])]}
        final={'checks':[row(source_id='s0',evidence=good['lines'][0])]}
        client=SequenceClient([brief(requirements=[REQ]),bad,initial,good,final])
        result=run_studio(CASE['prompt'],client=client)
        self.assertEqual(result['poem'],good)
        self.assertEqual(len(client.requests),5)
        self.assertTrue(result['checks']['requirements_confirmed'])
        self.assertTrue(client.requests[3][1]['revision']['content_evidence_to_resolve'])
