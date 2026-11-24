import unittest
from poetry_agent.editor_selection import select_revision,compliance_repair_priority

class SelectionTests(unittest.TestCase):
    def test_confirmed_compliance_repair_outranks_old_violation(self):
        before={'violations':[{'problem':'缺少原话'}]}
        after={'complete':True,'confirmed':True}
        self.assertTrue(compliance_repair_priority(before,after,[]))
        self.assertFalse(compliance_repair_priority(before,after,['too_long']))
        self.assertFalse(compliance_repair_priority(before,{'complete':True,'confirmed':False},[]))
        self.assertFalse(compliance_repair_priority({'confirmed':False},after,[]))
    def run_selection(self,**updates):
        args={'hard_issues':[], 'requirements':{'complete':True,'confirmed':True},
              'literary_review':{'assessment':{'decision':'keep'}},
              'comparison':{'selection_status':'consensus','order_consistent':True,'assessment':{'choice':'b'}}}
        args.update(updates)
        return select_revision({'title':'old','lines':['原稿']},{'title':'new','lines':['改稿']},**args)

    def test_consensus_does_not_override_unconfirmed_requirements(self):
        r=self.run_selection(requirements={'complete':True,'confirmed':False})
        self.assertFalse(r['adopted']);self.assertEqual(r['poem']['title'],'old')
        self.assertIn('requirements_not_confirmed',r['reasons'])

    def test_literary_revision_request_prevents_selection(self):
        self.assertFalse(self.run_selection(literary_review={'assessment':{'decision':'revise'}})['adopted'])

    def test_tie_disagreement_and_failure_retain_original(self):
        for c in ({},{'selection_status':'disagreement'},
                  {'selection_status':'consensus','order_consistent':True,'assessment':{'choice':'tie'}}):
            self.assertFalse(self.run_selection(comparison=c)['adopted'])

    def test_hard_failure_cannot_be_overridden_by_aesthetic_preference(self):
        self.assertFalse(self.run_selection(hard_issues=['too_many_lines'])['adopted'])

    def test_complete_evidence_can_select_without_certifying_quality(self):
        r=self.run_selection()
        self.assertTrue(r['adopted']);self.assertFalse(r['quality_verified'])
        self.assertFalse(r['requires_human_review'])
