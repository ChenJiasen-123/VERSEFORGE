import json
import unittest
from poetry_agent.proofreading import proofread

class Client:
    def __init__(self,rows):self.rows=rows
    def complete(self,*args,**kwargs):return {'content':json.dumps({'issues':self.rows})}

class ProofreadingTests(unittest.TestCase):
    def test_actual_line_quote_is_required(self):
        row={'line':1,'quote':':“谢谢','reason':'残留冒号','suggestion':'去掉开头冒号'}
        self.assertEqual(len(proofread({'lines':[':“谢谢大家”']},Client([row]))['issues']),1)
        with self.assertRaises(ValueError):proofread({'lines':['谢谢大家']},Client([row]))

    def test_empty_report_is_valid_and_not_quality_certification(self):
        self.assertFalse(proofread({'lines':['风——','还在吹']},Client([]))['quality_verified'])
