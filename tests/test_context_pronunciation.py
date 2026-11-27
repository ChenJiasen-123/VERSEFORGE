import json
import unittest
from poetry_agent.context_pronunciation import report_readings

class Client:
    def __init__(self,rows):self.rows=rows
    def complete(self,*args,**kwargs):return {'content':json.dumps({'readings':self.rows})}

class ContextPronunciationTests(unittest.TestCase):
    def test_reading_is_bound_to_actual_context_not_global_character(self):
        row={'id':'1-3','pinyin':'zhōng','sense':'之内','basis':'雨声中'}
        r=report_readings({'lines':['雨声中']},{'中'},Client([row]))
        self.assertFalse(r['historical_readings_verified'])
        row['basis']='中箭'
        with self.assertRaises(ValueError):report_readings({'lines':['雨声中']},{'中'},Client([row]))

    def test_no_proposal_is_allowed(self):
        self.assertEqual(report_readings({'lines':['中箭']},{'中'},Client([]))['readings'],[])
