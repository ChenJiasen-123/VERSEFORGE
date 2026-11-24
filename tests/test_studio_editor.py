import unittest
from unittest.mock import patch
from poetry_agent.studio import run_studio
from tests.test_studio import Client,brief,checked

class StudioEditorTests(unittest.TestCase):
    @patch('poetry_agent.editor.edit_rounds')
    def test_adopted_text_and_report_are_kept_together(self,edit):
        new={'title':'新稿','lines':['新的水位线']}
        report={'complete':True,'confirmed':True,'checks':[]}
        edit.return_value={'adopted':True,'poem':new,'drafts':[{'title':'原稿','lines':['水位线']},new],'rounds':[{'adopted':True,'requirements':report}]}
        c=Client([brief(),{'title':'原稿','lines':['水位线']},checked()])
        r=run_studio('写诗，不超过30行',client=c,independent_editor=True)
        self.assertEqual(r['poem'],new)
        self.assertIs(r['checks']['final_requirement_report'],report)
        self.assertEqual(len(r['drafts']),2)

    @patch('poetry_agent.editor.edit_rounds')
    def test_failed_editor_does_not_replace_original_report(self,edit):
        edit.return_value={'adopted':False,'drafts':[{'title':'原稿','lines':['水位线']}],'status':'editor_incomplete'}
        c=Client([brief(),{'title':'原稿','lines':['水位线']},checked()])
        r=run_studio('写诗，不超过30行',client=c,independent_editor=True)
        self.assertEqual(r['poem']['title'],'原稿')
        self.assertTrue(r['checks']['requirements_confirmed'])
