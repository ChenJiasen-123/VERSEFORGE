import unittest
import json
from unittest.mock import patch
from poetry_agent.editor import edit_once,edit_rounds
from poetry_agent.core import Task

class Client:
    def complete(self,*args,**kwargs):
        self.payload=json.loads(args[1])
        return {'content':'{"title":"新","lines":["新的一行"]}'}

class EditorTests(unittest.TestCase):
    def test_budget_exception_is_not_reported_as_service_outage(self):
        class Exhausted:
            def complete(self,*args,**kwargs):raise RuntimeError('编辑预算已用尽')
        r=edit_once('题',{'title':'题','lines':['正文']},Task('诗'),[],Exhausted(),proofread_text=True)
        self.assertEqual(r['failure_code'],'editor_budget_exhausted')
    @patch('poetry_agent.editor.proofread',side_effect=[{'issues':[{'quote':':','reason':'残留','suggestion':'删去'}]},{'issues':[]}])
    @patch('poetry_agent.editor.safe_review',return_value={'complete':True,'confirmed':True})
    @patch('poetry_agent.editor.review',return_value={'assessment':{'decision':'keep'}})
    def test_punctuation_only_repair_rechecked_without_human_selection(self,review,requirements,copyedit):
        r=edit_once('题',{'title':'新','lines':[':新的一行']},Task('诗','modern',30),[],Client(),proofread_text=True)
        self.assertEqual(r['status'],'copyedit_repair_selected');self.assertTrue(r['adopted'])
    @patch('poetry_agent.editor._metrical_target_and_report',side_effect=[({}, {'status':'failed'}),({}, {'status':'pass'})])
    @patch('poetry_agent.editor.safe_review',return_value={'complete':True,'confirmed':True})
    @patch('poetry_agent.editor.review',return_value={'assessment':{'decision':'keep'}})
    def test_failed_meter_forces_revision_despite_literary_keep(self,review,requirements,meter):
        r=edit_once('五绝',{'title':'原','lines':['旧的一行']},Task('诗','wujue',4,wujue_pattern='ze_no_rhyme'),[],Client())
        self.assertEqual(len(r['drafts']),2)
        self.assertNotEqual(r['status'],'no_revision_requested')
    @patch('poetry_agent.editor.safe_review',return_value={'confirmed':True,'complete':True})
    @patch('poetry_agent.editor.review',return_value={'assessment':{'decision':'keep'}})
    def test_reviewer_cannot_see_writer_rationale_or_internal_constraints(self,review,requirements):
        edit_once('允许温暖，不必解释',{'title':'原','lines':['正文']},
                  Task('内部摘要','modern',20,extra_requirements='选定方向：一律冷峻'),[],Client())
        t=review.call_args.args[1]
        self.assertEqual(t['topic'],'允许温暖，不必解释')
        self.assertNotIn('extra_requirements',t)
    @patch('poetry_agent.editor.safe_review',side_effect=[{'confirmed':False,'violations':[{'problem':'缺少原话'}]}, {'confirmed':True,'complete':True}])
    @patch('poetry_agent.editor.review',return_value={'assessment':{'decision':'keep'}})
    def test_known_violation_forces_repair_even_when_literary_reviewer_keeps(self,review,requirements):
        r=self.run_editor()
        self.assertTrue(r['adopted']);self.assertEqual(r['status'],'compliance_repair_selected')

    def test_call_budget_is_enforced_across_rounds(self):
        class BrokenClient:
            def __init__(self): self.calls=0
            def complete(self,*args,**kwargs):
                self.calls+=1
                raise RuntimeError('service failure')
        c=BrokenClient()
        r=edit_rounds('题',{'title':'原','lines':['原文']},Task('诗'),[],c,max_calls=1)
        self.assertEqual(c.calls,1);self.assertEqual(r['calls'],1)
        self.assertEqual(r['status'],'budget_exhausted')

    @patch('poetry_agent.editor.edit_once')
    def test_multiple_rounds_carry_feedback_without_human_selection(self,edit):
        old={'title':'原','lines':['原文']};new={'title':'新','lines':['新文']}
        edit.side_effect=[{'status':'original_retained','adopted':False,'poem':old,'drafts':[old,new]},
                          {'status':'revision_selected','adopted':True,'poem':new,'drafts':[old,new]},
                          {'status':'no_revision_requested','adopted':False,'poem':new,'drafts':[new]}]
        r=edit_rounds('题',old,Task('诗'),[],Client())
        self.assertEqual(r['poem'],new);self.assertEqual(len(r['rounds']),3)
        self.assertIn('上轮自动编辑记录',edit.call_args_list[1].args[2].extra_requirements)

    @patch('poetry_agent.editor._metrical_target_and_report',side_effect=[({}, {'status':'pass'}),({}, {'status':'unknown'})])
    @patch('poetry_agent.editor.review',return_value={'assessment':{'decision':'revise'}})
    def test_classical_unknown_meter_retains_original(self,review,meter):
        r=edit_once('五绝',{'title':'原','lines':['旧的一行']},Task('诗','wujue',4,wujue_pattern='ze_no_rhyme'),[],Client())
        self.assertEqual(r['status'],'revision_meter_unconfirmed')
        self.assertFalse(r['adopted']);self.assertEqual(r['poem']['title'],'原')

    @patch('poetry_agent.editor._metrical_target_and_report',side_effect=[({}, {'status':'pass'}),({}, {'status':'failed'})])
    @patch('poetry_agent.editor.review',return_value={'assessment':{'decision':'revise'}})
    def test_classical_failed_meter_retains_original(self,review,meter):
        c=Client()
        r=edit_once('五绝',{'title':'原','lines':['旧的一行']},Task('诗','wujue',4,wujue_pattern='ze_no_rhyme'),[],c)
        self.assertEqual(r['status'],'revision_meter_failed');self.assertFalse(r['adopted'])
        self.assertEqual(c.payload['revision']['metrical_feedback']['feedback_protocol'],'metrical-feedback-0.2')

    def run_editor(self):
        return edit_once('写一首诗',{'title':'原','lines':['旧的一行']},Task('诗','modern',30),['写一首诗'],Client())

    @patch('poetry_agent.editor.review',return_value={'assessment':{'decision':'keep'}})
    def test_keep_has_no_rewrite(self,review):
        r=self.run_editor();self.assertEqual(len(r['drafts']),1);self.assertFalse(r['adopted'])

    @patch('poetry_agent.editor.safe_review',return_value={'confirmed':False,'complete':True})
    @patch('poetry_agent.editor.review',return_value={'assessment':{'decision':'revise'}})
    def test_requirement_failure_retains_both_drafts(self,review,requirements):
        r=self.run_editor();self.assertEqual(len(r['drafts']),2)
        self.assertEqual(r['poem']['title'],'原');self.assertEqual(review.call_count,1)

    @patch('poetry_agent.editor.review',side_effect=ValueError('审读引用不在正文中'))
    def test_invalid_review_retains_original(self,review):
        r=self.run_editor();self.assertEqual(r['failure_code'],'quote_not_found');self.assertFalse(r['adopted'])

    @patch('poetry_agent.editor.compare_bidirectional',return_value={'selection_status':'consensus','order_consistent':True,'assessment':{'choice':'b'}})
    @patch('poetry_agent.editor.safe_review',return_value={'confirmed':True,'complete':True})
    @patch('poetry_agent.editor.review',side_effect=[{'assessment':{'decision':'revise'}},{'assessment':{'decision':'keep'}}])
    def test_rechecked_consensus_selects_new_text(self,review,requirements,comparison):
        r=self.run_editor();self.assertTrue(r['adopted']);self.assertEqual(r['poem']['title'],'新')
