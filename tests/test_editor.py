import unittest
from unittest.mock import patch
from poetry_agent.editor import edit_once
from poetry_agent.core import Task

class Client:
    def complete(self,*args,**kwargs):
        return {'content':'{"title":"新","lines":["新的一行"]}'}

class EditorTests(unittest.TestCase):
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
