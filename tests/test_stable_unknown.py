import unittest
from poetry_agent.meter_changes import stable_unknown_revision
from poetry_agent.prosody import Reading, validate

class StableUnknownTests(unittest.TestCase):
    def evidence(self, text):
        lexicon={c:[Reading('P','one','test')] for c in '甲乙'}
        return ({'pattern':'PP'}, validate([text], ['PP'], [], lexicon, 'test target'))
    def check(self, before, after):
        return stable_unknown_revision({'lines':[before]}, {'lines':[after]}, self.evidence(before), self.evidence(after))
    def test_preserved_unknown_does_not_freeze_confirmed_position(self):
        result=self.check('甲未','乙未')
        self.assertTrue(result['accepted'])
        self.assertFalse(result['overall_meter_certified'])
    def test_different_unknown_character_is_not_unchanged_uncertainty(self):
        result=self.check('甲未','甲末')
        self.assertFalse(result['accepted'])
    def test_new_unknown_at_previously_confirmed_position_is_rejected(self):
        self.assertFalse(self.check('甲未','末未')['accepted'])
    def test_missing_evidence_is_not_permission_to_adopt(self):
        result=stable_unknown_revision({'lines':['甲']},{'lines':['乙']},({}, {'status':'unknown'}),({}, {'status':'unknown'}))
        self.assertFalse(result['accepted'])

class StableUnknownEditorTests(unittest.TestCase):
    def test_stable_unknown_still_requires_independent_literary_selection(self):
        import json
        from unittest.mock import patch
        from poetry_agent.editor import edit_once
        from poetry_agent.core import Task
        class Client:
            def complete(self,*args,**kwargs):
                return {'content':json.dumps({'title':'题','lines':['乙未']})}
        evidence=StableUnknownTests().evidence
        for choice, adopted in [('b',True),('a',False)]:
            with self.subTest(choice=choice), \
                patch('poetry_agent.editor._metrical_target_and_report',side_effect=[evidence('甲未'),evidence('乙未')]), \
                patch('poetry_agent.editor.check',return_value=[]), \
                patch('poetry_agent.editor.safe_review',return_value={'confirmed':True,'complete':True}), \
                patch('poetry_agent.editor.review',side_effect=[{'assessment':{'decision':'revise'}},{'assessment':{'decision':'keep'}}]), \
                patch('poetry_agent.editor.compare_bidirectional',return_value={'selection_status':'consensus','order_consistent':True,'assessment':{'choice':choice}}):
                result=edit_once('写五绝',{'title':'题','lines':['甲未']},Task('题','wujue',wujue_pattern='ping_no_rhyme'),[],Client())
            self.assertEqual(result['adopted'],adopted)
            self.assertEqual(result['revision_meter']['status'],'unknown')
            self.assertFalse(result['revision_meter_guard']['overall_meter_certified'])
